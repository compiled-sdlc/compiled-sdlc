package org.springframework.samples.petclinic.customers.web;

import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.customers.model.Owner;
import org.springframework.samples.petclinic.customers.model.OwnerRepository;
import org.springframework.samples.petclinic.customers.model.Pet;
import org.springframework.samples.petclinic.customers.model.PetRepository;
import org.springframework.samples.petclinic.customers.model.PetType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.containsInAnyOrder;
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-103: an owner's pets can be listed in one request.
 */
@WebMvcTest(PetResource.class)
@ActiveProfiles("test")
class OwnerPetsListAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    PetRepository petRepository;

    @MockitoBean
    OwnerRepository ownerRepository;

    private Owner ownerWith(String... names) {
        Owner owner = new Owner();
        owner.setFirstName("George");
        owner.setLastName("Franklin");
        int id = 1;
        for (String name : names) {
            Pet pet = new Pet();
            pet.setId(id++);
            pet.setName(name);
            PetType type = new PetType();
            type.setId(6);
            type.setName("cat");
            pet.setType(type);
            owner.addPet(pet);
        }
        return owner;
    }

    @Test
    void shouldListThePetsOfAnOwner() throws Exception {
        given(ownerRepository.findById(1)).willReturn(Optional.of(ownerWith("Leo", "Basil")));

        mvc.perform(get("/owners/1/pets").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(2))
            .andExpect(jsonPath("$[*].name").value(containsInAnyOrder("Leo", "Basil")))
            .andExpect(jsonPath("$[0].type.id").value(6))
            .andExpect(jsonPath("$[0].owner").value("George Franklin"));
    }

    @Test
    void shouldAnswerAnEmptyArrayForAnOwnerWithNoPets() throws Exception {
        given(ownerRepository.findById(2)).willReturn(Optional.of(ownerWith()));

        mvc.perform(get("/owners/2/pets").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void shouldAnswerNotFoundForAnUnknownOwner() throws Exception {
        given(ownerRepository.findById(99)).willReturn(Optional.empty());

        mvc.perform(get("/owners/99/pets").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isNotFound());
    }
}
